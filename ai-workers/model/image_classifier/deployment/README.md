# Disaster Classifier API (Render + Hugging Face model storage)

## Files
- `app.py`: FastAPI application. Downloads the checkpoint from a public Hugging Face model repository at startup.
- `requirements.txt`: Python dependencies.
- `render.yaml`: Render Blueprint configuration.
- `.gitignore`: excludes local environments and model checkpoints from Git.

## Hugging Face setup
1. Create a **Model** repository on Hugging Face.
2. Upload your checkpoint, named `best_model.pt`.
3. Keep the repository public.
4. Copy the repository ID, in the form `USERNAME/REPOSITORY_NAME`.

The checkpoint must contain the keys `classes`, `img_size`, `model_name`, and `model`, matching the existing app's expected checkpoint format.

## Render setup
1. Push these files to GitHub (do not add the `.pt` file).
2. In Render, create a Web Service from the GitHub repository.
3. Select Python runtime and the Free plan.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Add environment variable:
   - `HF_MODEL_REPO_ID` = `YOUR_USERNAME/YOUR_MODEL_REPO`
   - `HF_MODEL_FILENAME` = `best_model.pt` (optional; this is the default)
7. Deploy. The checkpoint downloads from Hugging Face during startup.

## API
- `GET /health`
- `POST /predict` (multipart image field named `file`)
- `/docs`

## Important free-tier note
Render Free has limited RAM, CPU and ephemeral disk. A 100–500 MB checkpoint may download successfully but the model can still exceed the instance's memory while loading or predicting. If the service exits with an out-of-memory error, use a smaller/quantized model or a hosting plan with more RAM. Free services may sleep after inactivity, and the checkpoint may need to be downloaded again after a restart.

## Local run
Set `HF_MODEL_REPO_ID` to your public model repository ID, then:
`pip install -r requirements.txt`
`uvicorn app:app --reload`
