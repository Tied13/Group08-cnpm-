# Group08-cnpm-
bước 1. Clone project về máy (lần đầu tiên)

bash
git clone https://github.com/OWNER/REPO.git
cd REPO.
Bước 2. Kiểm tra branch hiện tại

bash
git branch
Nếu chưa ở main:


bash
git checkout main.
bước 3. Trước khi code, lấy code mới nhất

bash
git pull origin main
Bước này giúp đồng bộ code mà các thành viên khác đã push lên.

bước 4. Code và lưu thay đổi
Sau khi sửa code, chạy:


bash
git add .
git commit -m "Update feature".
Bước 5. Push code lên GitHub

bash
git push origin mai
