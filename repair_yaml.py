#!/usr/bin/env python3
import json, yaml, time, sys, re, pprint, traceback, argparse
from pathlib import Path

# with open('data/[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
#     items = yaml.safe_load(f)
#     query_dict = {item['uuid']: item for item in items}

# with open('data/手改[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
#     text = f.read()
#     parts = re.split(r'(^|\n)(?=- dockerfile_content: )', text)

# for part in parts:
#     try:
#         tmp_dict = yaml.safe_load(part)
#     except Exception as e:
#         print(part)
#         traceback.print_exc()
#         print("-"*80)

#         uuid = re.search(r'^\s*uuid: ([a-f0-9\-]{36})$', part, re.M).group(1)
#         print(yaml.dump([query_dict[uuid]], allow_unicode=True))
#         input("Press Enter to continue...")
#         print("="*80)

import docker, io, uuid, random, string

from camel.models import ModelFactory
from camel.tasks import Task
from camel.types import ModelPlatformType, ModelType
from camel.agents import ChatAgent, TaskPlannerAgent
from camel.interpreters import DockerInterpreter, SubprocessInterpreter


random.seed(time.time())

class DockerInterpreterWithInit(DockerInterpreter):
    def __init__(self, dockerfile_content, require_confirm=False, print_stdout=True, print_stderr=True):
        super().__init__(require_confirm=require_confirm, print_stdout=print_stdout, print_stderr=print_stderr)
        
        client = docker.from_env()

        if "CMD" not in dockerfile_content and "ENTRYPOINT" not in dockerfile_content:
            dockerfile_content += "\nCMD [\"tail\", \"-f\", \"/dev/null\"]"

        print(dockerfile_content, end="\n=========================================================================\n")
        dockerfile_fileobj = io.BytesIO(dockerfile_content.encode('utf-8'))
        image_tag = "camel-interpreter:latest"

        # Build custom image with input dockerfile_content
        try:
            image, build_logs = client.images.build(
                fileobj=dockerfile_fileobj,
                tag=image_tag,
                rm=True,  # Remove intermediate containers
                # forcerm=True # Force remove intermediate containers
            )

            for log in build_logs:
                if 'stream' in log:
                    print(log['stream'].strip())

            print("\n✅ Image built successfully!")

            print(f" -> ID: {image.id}")
            print(f" -> Tags: {image.tags}")
        except docker.errors.BuildError as e:
            print("\n❌ Error building the image!")
            
            for log in e.build_log:
                if 'stream' in log:
                    print(log['stream'].strip())
            raise
        except docker.errors.APIError as e:
            print(f"\n❌ Docker API Error")
            raise

        self._container = client.containers.run(
            image_tag,
            detach=True,
            name=f"camel-interpreter-{uuid.uuid4()}",
            entrypoint="",
            # command="tail -f /dev/null",
            # remove=True,          # Automatically remove the container when it exits
            sysctls={             # Equivalent to --sysctl
                'net.ipv4.ip_forward': '1'
            }
        )
    # def cleanup(self):
    #     try:
    #         if self._container:
    #             self._container.stop()
    #             # self._container.remove() is now safe to call because remove=True is gone
    #             print("✅ Container stopped and removed successfully.")
    #     except docker.errors.NotFound:
    #         # Container was already removed, which is fine.
    #         pass
    #     except Exception as e:
    #         traceback.print_exc()
    #         print(f"❌ Error during container cleanup: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # use args but not kwargs for portion parameter
    parser.add_argument('portion', type=int)
    parser.add_argument('index', type=int, default=0)
    parser.add_argument('uuid', type=str)
    args = parser.parse_args()

    with open('data/[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
        items = yaml.safe_load(f)

    items = items[len(items)*(args.portion-1)//4 + args.index:len(items)*args.portion//4]
    for index, item in enumerate(items):
        # for debugging specific uuid
        if args.uuid and item['uuid'] != args.uuid:
            continue
        
        print(index + args.index, item['uuid'])
        random_num = random.randint(10000,99999)
        try:
            dockerfile_content = string.Template(item['dockerfile_content']).safe_substitute(random_num=random_num)
            verification = string.Template(item['verification']).safe_substitute(random_num=random_num)
            
            interpreter = DockerInterpreterWithInit(dockerfile_content, 
                                                    require_confirm=False, print_stdout=True, print_stderr=True)
            
            # while input("quit?").strip().lower() != 'q':
            #     verification = input()
            print(verification)
            interpreter.run(code=verification, code_type="bash")
            interpreter.cleanup()
        except Exception as e:
            traceback.print_exc()
            print(f"Processing item {index+ args.index}/{len(items)+args.index}: \n{item['uuid']}\n\n")
            exit()

