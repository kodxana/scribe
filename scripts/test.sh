#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
    echo 'Usage: sh scripts/test.sh [path/to/lbry_rocksdb_ng.whl]' >&2
    exit 2
fi
wheel=${1:-}
case "$wheel" in
    ''|*/lbry_rocksdb_ng-*.whl|lbry_rocksdb_ng-*.whl) ;;
    *) echo 'Expected an lbry_rocksdb_ng wheel.' >&2; exit 2 ;;
esac
if [ -n "$wheel" ] && [ ! -f "$wheel" ]; then
    echo "Wheel not found: $wheel" >&2
    exit 2
fi
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
run_dir=$(mktemp -d)
container=
cleanup() {
    if [ -n "$container" ]; then
        docker rm -f "$container" >/dev/null
    fi
    rm -f "$run_dir/image.id" "$run_dir/binding/"*
    rmdir "$run_dir/binding" "$run_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir "$run_dir/binding"
# Keep the named build context present even when testing the published wheel.
touch "$run_dir/binding/placeholder"
binding=published
if [ -n "$wheel" ]; then
    cp "$wheel" "$run_dir/binding/"
    binding=local-wheel
fi
output_dir=${TEST_OUTPUT_DIR:-$repo_dir/ci-results/$binding}
mkdir -p "$output_dir"

docker build --platform linux/amd64 --progress=plain --iidfile "$run_dir/image.id" \
    --build-context "binding=$run_dir/binding" -f "$repo_dir/docker/Dockerfile.test" "$repo_dir"
container=$(docker create --platform linux/amd64 --network none --cpus 2 --memory 4g \
    "$(cat "$run_dir/image.id")")
status=0
docker start -a "$container" || status=$?
if [ "$status" -eq 0 ]; then
    status=$(docker inspect --format '{{.State.ExitCode}}' "$container")
fi
docker logs "$container" > "$output_dir/tests.log" 2>&1
docker cp "$container:/results/." "$output_dir/"
exit "$status"
