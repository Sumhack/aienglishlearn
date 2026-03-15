#!/bin/bash
# =============================================================================
# deploy_lambda.sh — Package and deploy the backend API to AWS Lambda
#
# Usage:
#   chmod +x deploy_lambda.sh
#   ./deploy_lambda.sh <lambda-function-name> <aws-region>
#
# Example:
#   ./deploy_lambda.sh ai-englishlearning ap-south-1
# =============================================================================

set -e

FUNCTION_NAME=${1:-"ai-englishlearning"}
REGION=${2:-"ap-south-1"}
DEPLOY_DIR="build"
ZIP_FILE="api_lambda.zip"

echo ""
echo "Deploying: $FUNCTION_NAME -> $REGION"
echo "-----------------------------------"

echo "Cleaning previous build..."
rm -rf "$DEPLOY_DIR" "$ZIP_FILE"

echo "Installing Linux-compatible dependencies..."
pip3 install \
    --platform manylinux2014_x86_64 \
    --target "./$DEPLOY_DIR" \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --upgrade \
    -r requirements-lambda.txt --quiet

echo "Copying app source..."
mkdir -p "$DEPLOY_DIR/app"
cp -r src/app/* "$DEPLOY_DIR/app"

echo "Zipping..."
cd "$DEPLOY_DIR"
zip -r "../$ZIP_FILE" . -x "*.pyc" -x "*/__pycache__/*" > /dev/null
cd ..

ZIP_SIZE=$(du -sh "$ZIP_FILE" | cut -f1)
echo "Created $ZIP_FILE ($ZIP_SIZE)"

echo "Uploading to AWS Lambda..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output json | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f'Runtime:   {r.get(\"Runtime\", \"N/A\")}')
print(f'Handler:   {r.get(\"Handler\", \"N/A\")}')
print(f'Modified:  {r.get(\"LastModified\", \"N/A\")}')
print(f'State:     {r.get(\"State\", \"N/A\")}')
"

echo ""
echo "Deployment complete."
echo "Check Lambda console -> Test tab to verify."
echo ""
