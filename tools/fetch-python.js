// 下载 Python 3.8.10 embeddable 与 get-pip（对齐服务器 venv 的 3.8.10）
const fs = require('fs');
const https = require('https');
const path = require('path');

const targets = [
  ['https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-amd64.zip', 'tools/py38.zip'],
  ['https://bootstrap.pypa.io/pip/3.8/get-pip.py', 'tools/get-pip.py'],
];

function download(url, dest) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const file = fs.createWriteStream(dest);
    https
      .get(url, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          file.close();
          return download(res.headers.location, dest).then(resolve, reject);
        }
        if (res.statusCode !== 200) {
          file.close();
          return reject(new Error(`${url} -> HTTP ${res.statusCode}`));
        }
        res.pipe(file);
        file.on('finish', () => file.close(() => resolve(dest)));
      })
      .on('error', reject);
  });
}

(async () => {
  for (const [url, dest] of targets) {
    try {
      await download(url, dest);
      console.log('OK', dest, fs.statSync(dest).size, 'bytes');
    } catch (e) {
      console.log('FAIL', url, e.message);
      process.exitCode = 1;
    }
  }
})();
