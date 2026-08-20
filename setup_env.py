import os

def create_structure(base_dir="."):
    """Creates the standard folder structure directly in the current directory."""
    
    # 1. Define the folder structure
    folders = [
        os.path.join(base_dir, "ai", "schemas"),
        os.path.join(base_dir, "ai", "prompts"),
        os.path.join(base_dir, "ai", "modules"),
        os.path.join(base_dir, "tests", "fixtures"),
        os.path.join(base_dir, "tests", "ai_eval")
    ]
    
    # 2. Define files to be created
    files = {
        os.path.join(base_dir, "ai", "schemas", "ai_outputs.py"): "",
        os.path.join(base_dir, "ai", "openai_client.py"): "# LLM client will go here\n",
        os.path.join(base_dir, "requirements.txt"): "pandas\nnumpy\nscipy\npydantic\nsqlalchemy\ncelery\n"
    }
    
    print(f"Creating folder structure in '{os.path.abspath(base_dir)}'...")

    # Create folders
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
            print(f"✅ Created folder: {folder}")
        except Exception as e:
            print(f"❌ Error creating folder {folder}: {e}")

    # Create files
    for file_path, content in files.items():
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ Created file: {file_path}")
        except Exception as e:
            print(f"❌ Error creating file {file_path}: {e}")
            
    print("\n✅ Structure created successfully!")

if __name__ == "__main__":
    create_structure()