import os

# Create a new directory
os.mkdir("new_directory")

# Change the current working directory
os.chdir("new_directory")

# Print the current working directory
print(os.getcwd())

# Remove the directory
os.chdir("..")
os.rmdir("new_directory")