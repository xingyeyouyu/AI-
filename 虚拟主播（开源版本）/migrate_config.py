import configparser
import sqlite3
import os
from pathlib import Path
from database import config_db

def migrate_config():
    # Initialize the database
    config_db.init_db()
    
    # Get the paths
    config_txt_path = Path(__file__).resolve().parent / "config.txt"
    db_path = Path(__file__).resolve().parent / "database" / "config.db"
    
    print(f"Migrating from {config_txt_path} to {db_path}")
    
    # Check if config.txt exists
    if not config_txt_path.exists():
        print("config.txt does not exist")
        return
    
    # Read config.txt
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str  # Preserve case
    cfg.read(config_txt_path, encoding="utf-8")
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Clear existing settings
    cur.execute("DELETE FROM settings")
    
    # Migrate settings using the internal _sections to avoid default value duplication
    count = 0
    # The _sections attribute holds the raw sections without default values inherited.
    for section_name, section_items in cfg._sections.items():
        for key, value in section_items.items():
            full_key = f"{section_name}.{key}"
            cur.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                (full_key, value),
            )
            count += 1
            print(f"Migrated: {full_key} = {value}")
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print(f"Migration complete. {count} settings migrated.")
    
    # Verify migration
    settings = config_db.get_all_settings()
    print(f"\nVerification: {len(settings)} settings in database:")
    for key, value in settings.items():
        print(f"  {key} = {value}")

if __name__ == "__main__":
    migrate_config() 
 
 
 
 
 