import requests
import json

def send_request_with_retry(url, max_retries=3, timeout=10):
    retries = 0
    while retries <= max_retries:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f'Retry {retries+1}/{max_retries}: {e}')
            retries += 1
    print('All retries failed. Giving up.')
    return None

def fetch_space_ops_data():
    api_endpoints = [
        'http://api.open-notify.org/iss-now.json',
        'http://api.open-notify.org/astros.json'        
    ]
    data = {}
    for endpoint in api_endpoints:
        response = send_request_with_retry(endpoint, max_retries=3, timeout=5)
        if response:
            data[endpoint] = response.json()
    return data

def save_data_to_file(data, filename):
    with open(filename, 'w') as file:
        json.dump(data, file, indent=4)

def main():
    data = fetch_space_ops_data()
    save_data_to_file(data, 'space_ops_data.json')
if __name__ == '__main__':
    main()