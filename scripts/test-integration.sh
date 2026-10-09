#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo 'Usage: sh scripts/test-integration.sh <SDK checkout> [path/to/lbry_rocksdb.whl]' >&2
    exit 2
fi
sdk_dir=$(CDPATH= cd -- "$1" && pwd)
wheel=${2:-}
case "$wheel" in
    ''|*/lbry_rocksdb-*.whl|lbry_rocksdb-*.whl) ;;
    *) echo 'Expected an lbry_rocksdb wheel.' >&2; exit 2 ;;
esac
if [ -n "$wheel" ] && [ ! -f "$wheel" ]; then
    echo "Wheel not found: $wheel" >&2
    exit 2
fi
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
run_dir=$(mktemp -d)
sdk_image=hub-sdk-test:$(basename "$run_dir")
cleanup() {
    for cid_file in "$run_dir/test.cid" "$run_dir/elastic.cid"; do
        if [ -s "$cid_file" ]; then
            docker rm -f "$(cat "$cid_file")" >/dev/null 2>&1 || true
        fi
    done
    docker image rm "$sdk_image" >/dev/null 2>&1 || true
    rm -f "$run_dir/test.cid" "$run_dir/elastic.cid" "$run_dir/image.id" "$run_dir/binding/"*
    rmdir "$run_dir/binding" "$run_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir "$run_dir/binding"
touch "$run_dir/binding/placeholder"
binding=published
if [ -n "$wheel" ]; then
    cp "$wheel" "$run_dir/binding/"
    binding=local-wheel
fi
output_dir=${TEST_OUTPUT_DIR:-$repo_dir/ci-results/resolve-$binding}
mkdir -p "$output_dir"

docker build --platform linux/amd64 --progress=plain --tag "$sdk_image" \
    -f "$sdk_dir/docker/Dockerfile.test" "$sdk_dir"
docker build --platform linux/amd64 --progress=plain --iidfile "$run_dir/image.id" \
    --build-context "sdk=docker-image://$sdk_image" --build-context "binding=$run_dir/binding" \
    -f "$repo_dir/docker/Dockerfile.integration" "$repo_dir"

es_image=docker.elastic.co/elasticsearch/elasticsearch:7.12.1@sha256:8e93628cef91f721bc9c4662f4a8f088752c2464fa966665413f175f8a96d268
es_id=$(docker run --detach --platform linux/amd64 --cidfile "$run_dir/elastic.cid" \
    --network none --cpus 2 --memory 2g --env discovery.type=single-node \
    --env xpack.security.enabled=false --env 'ES_JAVA_OPTS=-Xms512m -Xmx512m' "$es_image")
attempt=0
until docker exec "$es_id" curl -fsS --max-time 2 http://127.0.0.1:9200/ >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ] || [ "$(docker inspect --format '{{.State.Running}}' "$es_id")" != true ]; then
        docker logs "$es_id"
        exit 1
    fi
    sleep 1
done

# Share only Elasticsearch's isolated loopback network; publish no host ports.
status=0
docker run --init --platform linux/amd64 --cidfile "$run_dir/test.cid" \
    --network "container:$es_id" --cpus 4 --memory 4g --ulimit nofile=65536:65536 \
    "$(cat "$run_dir/image.id")" timeout --kill-after=10 "${TEST_TIMEOUT:-1800}" \
    sh ./test-resolve.sh || status=$?
test_id=$(cat "$run_dir/test.cid")
docker logs "$test_id" > "$output_dir/tests.log" 2>&1
docker cp "$test_id:/results/." "$output_dir/"
exit "$status"
