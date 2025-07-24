import requests
import os

BASE_URL = 'http://localhost:8000'  # 根据实际端口调整

def test_get_files():
    resp = requests.get(f'{BASE_URL}/api/files', params={'path': 'document'})
    print('文件列表:', resp.json())

def test_get_paths():
    resp = requests.get(f'{BASE_URL}/api/paths')
    print('目录列表:', resp.json())

def test_create_folder():
    # 新建 document/test_dir
    resp = requests.post(f'{BASE_URL}/api/folders', params={'path': 'document/test_dir'})
    print('新建目录:', resp.json())

def test_upload_file():
    # 先确保有一个测试文件
    test_file = 'test_upload.txt'
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write('hello world')
    with open(test_file, 'rb') as f:
        resp = requests.post(f'{BASE_URL}/api/files/upload', params={'path': 'document/test_dir'}, files={'file': f})
        print('上传文件:', resp.json())
    os.remove(test_file)

def test_delete_file():
    # 删除文件 document/test_dir/test_upload.txt
    resp = requests.delete(f'{BASE_URL}/api/files', params={'name': 'test_upload.txt', 'path': 'document/test_dir', 'type': 'file'})
    print('删除文件:', resp.json())

def test_delete_folder():
    # 删除目录 document/test_dir
    resp = requests.delete(f'{BASE_URL}/api/files', params={'name': 'test_dir', 'path': 'document', 'type': 'folder'})
    print('删除目录:', resp.json())

if __name__ == '__main__':
    test_get_files()
    test_get_paths()
    test_create_folder()
    test_upload_file()
    test_delete_file()
    test_delete_folder()
