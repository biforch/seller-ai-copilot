#!/bin/bash

source /opt/anaconda3/etc/profile.d/conda.sh

conda activate seller-ai

cd "$(dirname "$0")/backend"

uvicorn app.main:app --reload
