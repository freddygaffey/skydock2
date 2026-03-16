#!/bin/bash
# fetch_and_process_missions.sh
#
# Usage:
#   ./fetch_and_process_missions.sh          # SCP missions from RPi
#   ./fetch_and_process_missions.sh --local  # Copy missions from ~/Downloads instead
#
# 1. Fetch mission* folders (from RPi or ~/Downloads)
# 2. Store raw data in archive/drone_mission_raw/
# 3. Run mission_to_video.py on each mission
# 4. Collect processed videos in archive/processed_videos/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RPI_HOST="fred@rpi.local"
RPI_MISSION_PATH="~/skydock2/mission*"
DOWNLOADS_DIR="$HOME/Downloads"

RAW_DIR="$SCRIPT_DIR/archive/drone_mission_raw"
PROCESSED_DIR="$SCRIPT_DIR/archive/processed_videos"

# Create output directories
mkdir -p "$RAW_DIR"
mkdir -p "$PROCESSED_DIR"

# Step 1: Fetch mission folders
if [ "$1" = "--local" ]; then
    echo "=== Copying missions from $DOWNLOADS_DIR ==="
    found=0
    for m in "$DOWNLOADS_DIR"/mission*; do
        if [ -d "$m" ]; then
            cp -r "$m" "$RAW_DIR/"
            found=1
            echo "  Copied $(basename "$m")"
        fi
    done
    if [ "$found" -eq 0 ]; then
        echo "ERROR: No mission* folders found in $DOWNLOADS_DIR"
        exit 1
    fi
else
    echo "=== Fetching missions from $RPI_HOST ==="
    scp -r "$RPI_HOST:$RPI_MISSION_PATH" "$RAW_DIR/"

    if [ $? -ne 0 ]; then
        echo "ERROR: scp failed. Check that rpi.local is reachable and missions exist."
        exit 1
    fi
fi

echo "Raw missions saved to: $RAW_DIR"

# Step 2: Process each mission folder into a video
echo ""
echo "=== Processing missions ==="

for top_dir in "$RAW_DIR"/mission*; do
    if [ ! -d "$top_dir" ]; then
        continue
    fi

    # Process each timestamped subdirectory within the mission folder
    for mission in "$top_dir"/????-??-??_??-??-??; do
        if [ ! -d "$mission" ]; then
            continue
        fi

        mission_name="$(basename "$top_dir")_$(basename "$mission")"
        echo "Processing: $mission_name"

        if ! python3 "$SCRIPT_DIR/mission_to_video.py" "$mission"; then
            echo "  WARNING: Failed to process $mission_name, skipping"
            continue
        fi

        # Move the generated video to the processed folder
        video_file="$mission/mission_video.mp4"
        if [ -f "$video_file" ]; then
            mv "$video_file" "$PROCESSED_DIR/${mission_name}.mp4"
            echo "  -> $PROCESSED_DIR/${mission_name}.mp4"
        else
            echo "  WARNING: No video produced for $mission_name"
        fi
    done
done

echo ""
echo "=== Done ==="
echo "Raw missions:     $RAW_DIR"
echo "Processed videos: $PROCESSED_DIR"
