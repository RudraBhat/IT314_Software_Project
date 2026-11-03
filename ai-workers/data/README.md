# Rudra's text examples

`rudra_labelled_posts_draft.csv` contains 200 team-authored synthetic examples prepared as a labelling draft. They are all `train_only`; no synthetic item belongs in a test split. `label_draft` is a proposed label, not a final independent annotation: `labeler` intentionally says it is pending Rudra's review, and Neeti/Dhruvil columns are blank. The first 60 rows are marked `shared_for_review` for independent three-person labelling. Reconcile these labels with Neeti's dataset guideline before using them for model training.

`prompt_injection_posts.jsonl` is the ten-post adversarial set for the `/triage` contract test. These posts are test fixtures and must not be added to the classifier training corpus.
