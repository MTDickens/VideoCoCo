uv run --env-file .env scripts/generate_video.py \
    --agent pi \
    --prepare-only \
    --video-model h3-max \
    --input-dir examples/ballistic_pendulum_cardboard \
    --image-to-agent --image-to-ref2va \
    --output outputs/ballistic_pendulum_cardboard-draft.mp4
