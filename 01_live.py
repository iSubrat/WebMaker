import os
import json
import ftplib
import requests
import mysql.connector
from mysql.connector import Error
from openai import OpenAI
from ftplib import FTP, error_perm


# MySQL database credentials
host = os.environ['DB_HOST']
username = os.environ['DB_USERNAME']
password = os.environ['DB_PASSWORD']
database = os.environ['DB_NAME']

# FTP credentials
ftp_host = os.environ['FTP_SERVER']
ftp_username = os.environ['FTP_USERNAME']
ftp_password = os.environ['FTP_PASSWORD']

# OPEN AI credentials
openai_api_key = os.environ['OPENAI_API_KEY']

def read_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            return content
    except FileNotFoundError:
        return "File not found. Please check the file path."
    except Exception as e:
        return f"An error occurred: {e}"

def generate_text(prompt, model="gpt-4o-2024-05-13"):
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system",
                 "content": "user will give description & json values (key value pairs), where keys are variable names & values are text which is written on a corporate website. update the text for building a website related to description. you have to return only key value pairs as json without any additional text because your response is going to use in code."},
                {"role": "user", "content": prompt}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"An error occurred: {e}"

def make_json(prompt, length, i=0):
    new_values = ''
    if i>2:
        return Error('Maximum Try Reached!')
    try:
        generated_text = '{'+str(generate_text(prompt)).split('{')[1].split('}')[0]+'}'
        new_values = json.loads(generated_text)
        if len(new_values)==length:
            print(f'It has new_values: {len(new_values)}')
            return new_values
        else:
            print(f'It has new_values: {len(new_values)} while length must be {length}, Retrying!')
            print(type(generated_text), generated_text)
            make_json(prompt, i+1)
    except Exception as e:
        print(e)
        make_json(prompt, i+1)

def execute_query(db_host, db_username, db_password, db_database, query):
    try:
        # Connect to the MySQL server
        connection = mysql.connector.connect(
            host=db_host,
            user=db_username,
            password=db_password,
            database=db_database
        )

        if connection.is_connected():
            print("Connected to MySQL database")
        cursor = connection.cursor()
        cursor.execute(query)

        # Fetch all the rows
        row = cursor.fetchone()

        # Print the rows
        if row:
            id = row[0]
            description = row[1]
            print('Debug A: ', id, description)

            while cursor.nextset():
                pass
            values = read_file('demo-corporate.json')
            file_path = "demo-corporate.html"
            html_content = read_file(file_path)
            prompt = f"Description:\n{description}\n\n\nValues:\n{values}"
            # generated_text = '{'+str(generate_text(prompt)).split('{')[1].split('}')[0]+'}'
            # print(type(generated_text), generated_text)
            # new_values = json.loads(generated_text)
            new_values = make_json(prompt, length=len(json.loads(values)))
            for k, v in new_values.items():
                html_content = html_content.replace(k, v)
            upload_to_ftp(ftp_host, ftp_username, ftp_password, file_path, html_content, id)
            
            update_query = """UPDATE app_descriptions SET status = 'COMPLETED' WHERE id = %s;"""
            if connection.is_connected():
                print("Connected to MySQL database")
            else:
                connection = mysql.connector.connect(
                    host=db_host,
                    user=db_username,
                    password=db_password,
                    database=db_database
                )
                cursor = connection.cursor()
                print("Re-Connected to MySQL database")
            cursor.execute(update_query, (id,))
            connection.commit()
            print("Status column updated to 'COMPLETED'")
            url = "http://server.appcollection.in/delete_appmaker.php"
            response = requests.get(url)
            if response.status_code == 200:
                print("Request was successful!")
                print(response.content)
            else:
                print(f"Request failed with status code: {response.status_code}")
        else:
            raise RuntimeError("There is no website for build.")

        # Close the cursor and connection
        cursor.close()
        connection.close()

    except mysql.connector.Error as e:
        print("Error executing query:", e)

def upload_to_ftp(ftp_host, ftp_username, ftp_password, filename, content, id):
    with FTP(ftp_host) as ftp:
        ftp.login(ftp_username, ftp_password)
        
        # Prepare the directory path
        directory = f'LIVE/{id}/'
        
        # Attempt to create and navigate to each part of the path
        try:
            ftp.cwd(directory)  # Try to change to the full directory path
        except error_perm as e:
            # If the directory does not exist, create it
            print("Directory does not exist, attempting to create:", directory)
            # Split the directory to handle each part
            parts = directory.split('/')
            current_path = ''
            for part in parts:
                if not part:
                    # Skip empty parts (e.g., leading '/')
                    continue
                current_path += f"/{part}"
                try:
                    ftp.cwd(current_path)
                except error_perm:
                    print(f"Creating directory: {current_path}")
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
        
        # Write the content to a file locally before uploading
        with open(filename, 'w') as file:
            file.write(content)
        
        # Upload the file
        with open(filename, 'rb') as file:
            ftp.storbinary(f'STOR {filename}', file)

        print(f"Uploaded {filename} to FTP.")


if __name__ == "__main__":
    try:  
      # Example query
      client = OpenAI(api_key=openai_api_key)
      query = """SELECT * FROM app_descriptions WHERE status = 'PENDING' ORDER BY id DESC LIMIT 1;"""
  
      # Execute the query
      execute_query(host, username, password, database, query)
    except Exception as e:
      raise RuntimeError("Process Aborted.")
