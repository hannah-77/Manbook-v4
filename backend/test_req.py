import requests

def test():
    try:
        with open('test.txt', 'w', encoding='utf-8') as f:
            f.write('Ini adalah teks percobaan untuk memeriksa deteksi bahasa.')
        
        with open('test.txt', 'rb') as f:
            res = requests.post('http://127.0.0.1:8000/detect-language', files={'file': f})
            print(f'Status: {res.status_code}')
            print(f'Response: {res.text}')
    except Exception as e:
        print(f'Error: {e}')

if __name__ == '__main__':
    test()
