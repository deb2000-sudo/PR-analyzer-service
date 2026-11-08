# PR Analyzer Service

Reviews a GitHub pull request for Contributor Conclave. The Next.js app sends the saved pull request, and this service returns the summary, insights, and suggested scores that the score dialog already accepts.

The service listens on `0.0.0.0` and `$PORT`. Cloud Run sets `PORT`.

## Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `ANALYSIS_TOKEN` in `.env`. Use the same value as `PR_ANALYSIS_TOKEN` in Contributor Conclave. Set `GITHUB_TOKEN` when check results and the linked issue should be read from GitHub.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

In Contributor Conclave `.env`:

```bash
PR_ANALYSIS_URL=http://127.0.0.1:8080/review
PR_ANALYSIS_TOKEN=<the same ANALYSIS_TOKEN>
```

Restart `npm run dev`, then use AI Analysis on a mentor pull request.

`POST /` and `POST /review` accept the same JSON. `GET /health` is open so Cloud Run can probe it. Review requests must send `Authorization: Bearer <ANALYSIS_TOKEN>`.

The request may include `config`. When it is omitted, quality, merge readiness, checks, and coaching all run, and suggested scores are returned.

Firestore is off locally. On Cloud Run, `FIRESTORE_ENABLED=true` stores the summary and scores in the `prAnalyses` collection. The pull request description and diff are not stored. The runtime service account needs Firestore write access. Do not put a Firebase private key in the image or in Cloud Build.

## Cloud Run

`cloudbuild.yaml` builds this directory, pushes `pr-analyzer-service` to the existing `contributor-conclave` Artifact Registry repository in `us-central1`, and deploys a separate Cloud Run service. Create these Secret Manager secrets before the first deploy, without putting their values in the build file:

- `pr-analyzer-token`
- `pr-analyzer-github-token`

Create a runtime service account `pr-analyzer-run` that can read those two secrets and write to Firestore. The trigger for this file should use this directory as its source, so a change here does not rebuild the Next.js app.
