#!/bin/bash

SUITE_NAME=${1:-guest_login}
TEST_SCRIPT="$SUITE_NAME/run_test.py"

if [ ! -f "testcases/$TEST_SCRIPT" ]; then
    echo "Error: Test case not found at 'testcases/$TEST_SCRIPT'"
    exit 1
fi

TEST_DIR=$(dirname "testcases/$TEST_SCRIPT")
OUTPUT_DIR="$TEST_DIR/output"

mkdir -p "$OUTPUT_DIR"

# 1. Kill old processes
echo "Checking for processes on ports 3000 and 8000..."
PIDS=$(lsof -ti:3000,8000)

if [ -n "$PIDS" ]; then
  echo "Killing processes: $PIDS"
  kill -9 $PIDS
  echo "Processes killed."
else
  echo "No processes found on ports 3000 or 8000."
fi

# 2. Start server in background
# We redirect input from /dev/null to prevent "suspended (tty input)" errors
echo "Starting Reflex server in background..."
echo "Logs will be written to $OUTPUT_DIR/reflex.log"
poetry run reflex run < /dev/null > "$OUTPUT_DIR/reflex.log" 2>&1 &
SERVER_PID=$!
echo "Reflex Server started with PID: $SERVER_PID"

# 3. Wait for server to be alive
echo "Waiting for server to listen on ports 3000 & 8000..."
MAX_RETRIES=60
for ((i=1; i<=MAX_RETRIES; i++)); do
    # Check if both ports are being listened to
    if lsof -i :3000 >/dev/null 2>&1 && lsof -i :8000 >/dev/null 2>&1; then
        echo "Server is up and running on ports 3000 & 8000!"
        
        # 4. Run the test script
        # TEST_SCRIPT is defined at the top
        echo "---------------------------------------------------"
        echo "Running Playwright test (testcases/$TEST_SCRIPT)..."
        echo "---------------------------------------------------"
        poetry run python testcases/"$TEST_SCRIPT"
        TEST_EXIT_CODE=$?
        
        echo "---------------------------------------------------"
        if [ $TEST_EXIT_CODE -eq 0 ]; then
            echo "Test passed!"
        else
            echo "Test failed with exit code $TEST_EXIT_CODE"
        fi
        
        echo "Stopping Reflex server (PID $SERVER_PID)..."
        kill $SERVER_PID 2>/dev/null
        
        echo "You can check logs in '$OUTPUT_DIR/reflex.log'"
        exit $TEST_EXIT_CODE
    fi
    
    # Check if process died early
    if ! ps -p $SERVER_PID > /dev/null; then
        echo "Server process $SERVER_PID died unexpectedly!"
        cat "$OUTPUT_DIR/reflex.log"
        exit 1
    fi
    
    echo "Waiting for server... ($i/$MAX_RETRIES)"
    sleep 2
done

echo "Server failed to start within timeout."
kill $SERVER_PID 2>/dev/null
exit 1
