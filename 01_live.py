import os
import json
import ftplib
import requests
import mysql.connector
from mysql.connector import Error
from openai import OpenAI
from ftplib import FTP, error_perm

# Configuration
CONFIG = {
    'db_host': os.environ['DB_HOST'],
    'db_username': os.environ['DB_USERNAME'],
    'db_password': os.environ['DB_PASSWORD'],
    'db_name': os.environ['DB_NAME'],
    'ftp_host': os.environ['FTP_SERVER'],
    'ftp_username': os.environ['FTP_USERNAME'],
    'ftp_password': os.environ['FTP_PASSWORD'],
    'openai_api_key': os.environ['OPENAI_API_KEY'],
    'file_structure': '01_file_structure.json',
}

# Initialize OpenAI client
client = OpenAI(api_key=CONFIG['openai_api_key'])

def read_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except Exception as e:
        raise IOError(f"Error reading file {file_path}: {e}")

def generate_text(prompt, theme, model="gpt-4o-2024-05-13"):
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"The user will provide a description and JSON values (key-value pairs), where keys are variable names and values are text written on a website. existing values are available for just giving you idea which kind of & what length of text needs to write. Update the text to make website related to the provided description while preserving the original names for common buttons such as 'home', 'about us', 'contact us', etc. Ensure that the response maintains the same number of key-value pairs, only replacing the values without adding or deleting any keys. The response should contain only the updated key-value pairs in JSON format, without any additional text, as it will be used directly in the code."},
                {"role": "user", "content": prompt}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"Error generating text: {e}")

def decide_theme(description, model="gpt-4o-2024-05-13"):
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"The user will provide a description. you have to choose a website template for him by looking at description. Determine which template would be the best. Respond with only the template name from the following options: ['demo-consulting', 'demo-startup', 'demo-accounting', 'demo-restaurant', 'demo-charity', 'demo-architecture', 'demo-corporate', 'demo-ebook', 'demo-hosting', 'demo-application', 'demo-elearning', 'demo-medical', 'demo-business', 'demo-marketing', 'demo-photography', 'demo-magazine', 'demo-lawyer', 'demo-barber', 'demo-conference', 'demo-freelancer', 'demo-finance', 'demo-blogger']."},
                {"role": "user", "content": description}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"Error generating text: {e}")


def make_json(prompt, length, theme, retries=0):
    if retries > 2:
        raise RuntimeError('Maximum retries reached for generating JSON.')

    try:
        generated_text = '{' + str(generate_text(prompt, theme)).split('{')[1].split('}')[0] + '}'
        new_values = json.loads(generated_text)

        if len(new_values) == length:
            return new_values
        else:
            print(f"Generated JSON length mismatch. Expected {length}, got {len(new_values)}. Retrying...")
            return make_json(prompt, length, theme, retries + 1)
    except Exception as e:
        print(f"Error in make_json: {e}. Retrying...")
        return make_json(prompt, length, theme, retries + 1)

def connect_to_database():
    try:
        connection = mysql.connector.connect(
            host=CONFIG['db_host'],
            user=CONFIG['db_username'],
            password=CONFIG['db_password'],
            database=CONFIG['db_name']
        )
        if connection.is_connected():
            print("Connected to MySQL database")
            return connection
    except Error as e:
        raise RuntimeError(f"Error connecting to MySQL database: {e}")

def fetch_pending_web_description(connection):
    query = "SELECT * FROM web_descriptions WHERE status = 'PENDING' ORDER BY id DESC LIMIT 1;"
    cursor = connection.cursor()
    cursor.execute(query)
    return cursor.fetchone()

def update_status_to_building(connection, id):
    query = "UPDATE web_descriptions SET status = 'BUILDING' WHERE id = %s;"
    cursor = connection.cursor()
    cursor.execute(query, (id,))
    connection.commit()
    print(f"Status updated to BUILDING for id: {id}")

def update_status_to_completed(connection, id):
    query = "UPDATE web_descriptions SET status = 'COMPLETED' WHERE id = %s;"
    cursor = connection.cursor()
    cursor.execute(query, (id,))
    connection.commit()
    print(f"Status updated to COMPLETED for id: {id}")

def load_file_structure():
    try:
        with open(CONFIG['file_structure'], 'r') as f:
            return json.load(f)
    except Exception as e:
        raise IOError(f"Error loading file structure: {e}")

def upload_to_ftp(ftp_host, ftp_username, ftp_password, filename, content, id):
    with FTP(ftp_host) as ftp:
        ftp.login(ftp_username, ftp_password)
        directory = f'LIVE/{id}/'
        
        try:
            ftp.cwd(directory)
        except error_perm:
            parts = directory.split('/')
            current_path = ''
            for part in parts:
                if not part:
                    continue
                current_path += f"/{part}"
                try:
                    ftp.cwd(current_path)
                except error_perm:
                    print(f"Creating directory: {current_path}")
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
        
        with open(filename, 'w') as file:
            file.write(content)
        
        with open(filename, 'rb') as file:
            ftp.storbinary(f'STOR {filename}', file)
        print(f"Uploaded {filename} to FTP in directory: {directory}")

def process_file(j, file_key, description, theme, id):
    values_file = f'{file_key}.json'
    html_file = f'{file_key}.html'
    values = read_file(values_file)
    html_content = read_file(html_file)
    prompt = f"Description:\n{description}\n\n\nValues:\n{values}"
    new_values = make_json(prompt, length=len(json.loads(values)), theme=theme)

    for k, v in new_values.items():
        html_content = html_content.replace(k, v)

    # Upload the processed HTML file
    upload_to_ftp(CONFIG['ftp_host'], CONFIG['ftp_username'], CONFIG['ftp_password'], html_file, html_content, id)

    # Only create and upload index.html once, for the first file processed (j == 0)
    if j == 0:
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Customized Website</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            display: flex;
            flex-direction: column;
        }}
        #content-frame {{
            width: 100%;
            height: calc(100vh - 80px); /* Space at the bottom for the note and button */
            border: none;
        }}
        #note-container {{
            padding: 10px;
            background-color: #000000;
            text-align: center;
            font-family: Arial, sans-serif;
            font-size: 16px;
            color: #ffffff;
        }}
        #contact-button {{
            margin-top: 10px;
            padding: 10px 20px;
            font-size: 16px;
            color: white;
            background-color: #FF7A0F;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
        }}
        #contact-button:hover {{
            background-color: #45a049;
        }}
    </style>
</head>
<body>

    <!-- Main website content loaded in an iframe -->
    <iframe id="content-frame" src="./{html_file}"></iframe>

    <!-- Note and contact section -->
    <div id="note-container">
        <p>Need a few more customizations? Our developer team is here to help! Receive the source code and have your website live in just 24 hours.</p>
        <a id="contact-button" href="https://wa.me/916397285262?text=Hi%20Developer,%20I%20need%20assistance%20with%20my%20website%20customizations."
           target="_blank">Contact Developer</a>
    </div>

</body>
</html>
"""

        # Set index.html as the filename and upload it
        html_file = 'index.html'
        upload_to_ftp(CONFIG['ftp_host'], CONFIG['ftp_username'], CONFIG['ftp_password'], html_file, html_content, id)

def main():
    try:
        connection = connect_to_database()
        row = fetch_pending_web_description(connection)

        if row:
            if len(row) < 5:
                raise ValueError("Expected at least 5 columns in the database row.")

            id, description, theme, _, user_type = row[:5]
            update_status_to_building(connection, id)
            print(f"Processing id: {id}, theme: {theme}, user_type: {user_type}")
            if theme == 'ai':
                i=0
                while theme not in ['demo-consulting', 'demo-startup', 'demo-accounting', 'demo-restaurant', 'demo-charity', 'demo-architecture', 'demo-corporate', 'demo-ebook', 'demo-hosting', 'demo-application', 'demo-elearning', 'demo-medical', 'demo-business', 'demo-marketing', 'demo-photography', 'demo-magazine', 'demo-lawyer', 'demo-barber', 'demo-conference', 'demo-freelancer', 'demo-finance', 'demo-blogger']:
                    if i>2:
                        raise RuntimeError('AI Tried Maximum times to decide theme.')
                    theme = decide_theme(f'Description: """{description}"""')
                    i+=1
                    print(f'AI decided: {theme}')
                print(f"Processing id: {id}, theme: {theme}, user_type: {user_type}")

            file_structure = load_file_structure()

            if theme in file_structure:
                files_to_process = file_structure[theme]
                if user_type == 'FREE':
                    files_to_process = files_to_process[:1]

                for j, file_key in enumerate(files_to_process):
                    print(f"Processing file: {file_key}")
                    process_file(j, file_key, description, theme, id)

                connection = connect_to_database()
                update_status_to_completed(connection, id)

                response = requests.get("http://server.appcollection.in/delete_webmaker.php")
                if response.status_code == 200:
                    print("Request to external URL was successful!")
                else:
                    print(f"Request to external URL failed with status code: {response.status_code}")
            else:
                raise RuntimeError(f"No files associated with theme: {theme}")

        else:
            raise RuntimeError("No pending website found.")

    except Exception as e:
        print(f"Process aborted: {e}")

    finally:
        if 'connection' in locals() and connection.is_connected():
            connection.close()
            print("Database connection closed.")

if __name__ == "__main__":
    main()
