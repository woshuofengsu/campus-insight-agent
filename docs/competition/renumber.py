"""把技术报告里所有章节号重排一遍，改成连续编号。"""
import re, os

NUM_MAP = {
    '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,
    '八':8,'九':9,'十':10,'十一':11,'十二':12,'十三':13,
    '十四':14,'十五':15,'十六':16,'十七':17,'十八':18,
}
REV = {v:k for k,v in NUM_MAP.items()}

fdir = os.path.dirname(os.path.abspath(__file__))
fpath = os.path.join(fdir, '技术实现报告.md')

with open(fpath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

counter = 0
for i, line in enumerate(lines):
    for cn in NUM_MAP:
        if line.startswith(f'## {cn}、'):
            counter += 1
            rest = line[len(f'## {cn}、'):]
            lines[i] = f'## {REV[counter]}、{rest}'
            break

with open(fpath, 'w', encoding='utf-8') as f:
    f.writelines(lines)

# 打印结果
for i, line in enumerate(lines):
    for cn in NUM_MAP:
        if line.startswith(f'## {cn}、'):
            rest = line[len(f'## {cn}、'):].strip()
            print(f"  {cn}、{rest}")
            break
print("Done!")
