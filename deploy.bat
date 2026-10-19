@echo off
cd /d E:\stock_analyzer
git branch -M master main
git add portfolio.py web_app.py templates\index.html
git commit -m "feat: portfolio management and batch analysis"
git push -u origin main -f
pause
