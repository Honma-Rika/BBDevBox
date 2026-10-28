# Dataset and historical results

The inherited files contain Dockerfile-based CLI tasks and historical model results. The loader preserves UUID, problem, dockerfile_content, verification, subdomain, keyword, and level. New trusted local fixtures may additionally provide setup without a Dockerfile.

The repository snapshot supplied for this migration did not contain an upstream dataset citation, task-generation methodology, collection dates, model sampling parameters, or a dataset license. The new MIT code license does not establish redistribution rights for inherited dataset/result content. Maintainers should complete those provenance fields before publishing the data as a separately licensed release.

Historical results are observations, not claims about currently available model versions. Some tasks depend on external services, mutable base images, package repositories, or environment-specific service managers. Keep the original files intact; report task exclusions and environment failures explicitly instead of silently repairing a dataset during a run. Use pinned base-image digests and controlled mirrors in a curated reproducibility track.

Skills learned from these tasks should be kept in a training collection. Do not use near-duplicate tasks or task-specific answers in a held-out evaluation memory corpus.
