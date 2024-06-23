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
                {"role": "system", "content": f"user will give description & json values (key value pairs), where keys are variable names & values are text which is written on a {theme} website. update the text for building a website related to description. you have to return only key value pairs as json without any additional text because your response is going to use in code."},
                {"role": "user", "content": prompt}
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
            return make_json(prompt, length, theme, retries + 1)
    except Exception as e:
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
            return connection
    except Error as e:
        raise RuntimeError(f"Error connecting to MySQL database: {e}")

def fetch_pending_app_description(connection):
    query = "SELECT * FROM app_descriptions WHERE status = 'PENDING' ORDER BY id DESC LIMIT 1;"
    cursor = connection.cursor()
    cursor.execute(query)
    return cursor.fetchone()

def update_status_to_completed(connection, id):
    query = "UPDATE app_descriptions SET status = 'COMPLETED' WHERE id = %s;"
    cursor = connection.cursor()
    cursor.execute(query, (id,))
    connection.commit()

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
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
        
        with open(filename, 'w') as file:
            file.write(content)
        
        with open(filename, 'rb') as file:
            ftp.storbinary(f'STOR {filename}', file)

def process_file(file_key, description, theme, id):
    values_file = f'{file_key}.json'
    html_file = f'{file_key}.html'
    values = read_file(values_file)
    html_content = read_file(html_file)
    prompt = f"Description:\n{description}\n\n\nValues:\n{values}"
    new_values = make_json(prompt, length=len(json.loads(values)), theme=theme)

    for k, v in new_values.items():
        html_content = html_content.replace(k, v)

    upload_to_ftp(CONFIG['ftp_host'], CONFIG['ftp_username'], CONFIG['ftp_password'], html_file, html_content, id)

def main():
    try:
        connection = connect_to_database()
        row = fetch_pending_app_description(connection)

        if row:
            id, description, theme, _, user_type = row
            file_structure = load_file_structure()

            if theme in file_structure:
                files_to_process = file_structure[theme]
                if user_type == 'FREE':
                    files_to_process = files_to_process[:1]

                for file_key in files_to_process:
                    process_file(file_key, description, theme, id)

                update_status_to_completed(connection, id)

                response = requests.get("http://server.appcollection.in/delete_appmaker.php")
                if response.status_code == 200:
                    print("Request was successful!")
                else:
                    print(f"Request failed with status code: {response.status_code}")
            else:
                raise RuntimeError(f"No files associated with theme: {theme}")

        else:
            raise RuntimeError("No pending app descriptions found.")

    except Exception as e:
        print(f"Process aborted: {e}")

    finally:
        if 'connection' in locals() and connection.is_connected():
            connection.close()

if __name__ == "__main__":
    main()
