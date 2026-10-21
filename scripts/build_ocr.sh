#!/bin/sh
# Builds the offline macOS Vision OCR helper used for scanned PDFs and images.
set -e
cd "$(dirname "$0")/.."
mkdir -p bin
swiftc -O tools/vision_ocr.swift -o bin/vision_ocr
echo "Built bin/vision_ocr"
