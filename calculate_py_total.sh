# Calculate the total number of lines of Python code in the current directory,
echo "Calculating total lines of Python code..."
# excluding files in the 'testcases' directory, '__pycache__' directories, and
# the '.venv' directory.
find . -name "*.py" \
	-not -path "./testcases/*" \
	-not -path "*/__pycache__/*" \
	-not -path "./.venv/*" \
	-not -path "./.web/*" \
	| xargs wc -l