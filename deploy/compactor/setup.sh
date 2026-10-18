#!/bin/sh
# Deploy the nightly compactor: service account, data bucket, bucket IAM, image, Cloud Run job, 02:30 ET schedule.
#   sh deploy/compactor/setup.sh --project P --runs-bucket B --data-bucket D [--region R] [--github-repos o/r,o/r2]
#                                [--dry-run]
# --dry-run prints the gcloud commands and the rendered job instead of running them. Re-running is safe: resources
# that already exist are kept, and the job and schedule are updated.
set -eu
usage() { sed -n '3,7p' "$0" >&2; exit 2; }
PROJECT="" RUNS="" DATA="" REGION="us-east1" REPOS="" DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT=$2; shift 2 ;;
    --runs-bucket) RUNS=${2#gs://}; shift 2 ;;
    --data-bucket) DATA=${2#gs://}; shift 2 ;;
    --region) REGION=$2; shift 2 ;;
    --github-repos) REPOS=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$PROJECT" ] && [ -n "$RUNS" ] && [ -n "$DATA" ] || usage

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
NAME=flightdeck-compactor
SA="$NAME@$PROJECT.iam.gserviceaccount.com"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/flightdeck/compactor:latest"
G="--project $PROJECT"

run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
exists_ok() { run "$@" || echo "  (already exists; kept)"; }

run gcloud services enable run.googleapis.com cloudscheduler.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com $G
exists_ok gcloud iam service-accounts create $NAME --display-name "flightdeck compactor" $G
# The data plane's bucket: private, like the outbox (ADR-0002). The outbox bucket is hangar's (its terraform makes it).
exists_ok gcloud storage buckets create "gs://$DATA" --location "$REGION" --uniform-bucket-level-access \
  --public-access-prevention $G
# Read the outbox, write the data plane; nothing else (no hangar token, no project-wide roles).
run gcloud storage buckets add-iam-policy-binding "gs://$RUNS" --member "serviceAccount:$SA" \
  --role roles/storage.objectViewer $G
run gcloud storage buckets add-iam-policy-binding "gs://$DATA" --member "serviceAccount:$SA" \
  --role roles/storage.objectAdmin $G
if [ -n "$REPOS" ]; then
  # The secret holds a read-only GitHub token: gcloud secrets create flightdeck-github-token --data-file=-
  run gcloud secrets add-iam-policy-binding flightdeck-github-token --member "serviceAccount:$SA" \
    --role roles/secretmanager.secretAccessor $G
fi
exists_ok gcloud artifacts repositories create flightdeck --repository-format docker --location "$REGION" $G
run gcloud builds submit "$ROOT" --config "$HERE/cloudbuild.yaml" --substitutions "_IMAGE=$IMAGE" $G

JOB=$(mktemp)
trap 'rm -f "$JOB"' EXIT
FILTER='/# github$/d'
[ -n "$REPOS" ] && FILTER='s/  # github$//'
sed -e "$FILTER" -e "s|\${SERVICE_ACCOUNT}|$SA|; s|\${IMAGE}|$IMAGE|; s|\${RUNS_BUCKET}|$RUNS|" \
  -e "s|\${DATA_BUCKET}|$DATA|g; s|\${GITHUB_REPOS}|$REPOS|" "$HERE/cloudrun-job.yaml" > "$JOB"
[ "$DRY" = 1 ] && sed 's/^/    /' "$JOB"
run gcloud run jobs replace "$JOB" --region "$REGION" $G
# Cloud Scheduler calls the job as the same service account, which may run only this job.
run gcloud run jobs add-iam-policy-binding $NAME --member "serviceAccount:$SA" --role roles/run.invoker \
  --region "$REGION" $G
URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$NAME:run"
if [ "$DRY" = 1 ] || ! gcloud scheduler jobs describe $NAME-nightly --location "$REGION" $G > /dev/null 2>&1; then
  run gcloud scheduler jobs create http $NAME-nightly --location "$REGION" --schedule "30 2 * * *" \
    --time-zone America/New_York --uri "$URI" --http-method POST --oauth-service-account-email "$SA" $G
else
  run gcloud scheduler jobs update http $NAME-nightly --location "$REGION" --schedule "30 2 * * *" \
    --time-zone America/New_York --uri "$URI" --http-method POST --oauth-service-account-email "$SA" $G
fi
echo "done: run it now with  gcloud run jobs execute $NAME --region $REGION $G"
echo "hangar's terraform (deploy/terraform/gke) keeps the outbox grant too with:"
echo "  run_bucket_readers = [\"serviceAccount:$SA\"]"
echo "check a night with:  FLIGHTDECK_DATA_URI=gs://$DATA/parquet/v1 flightdeck query 'select dt, count(*) from runs group by dt'"
