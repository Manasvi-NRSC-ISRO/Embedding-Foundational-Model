import re, glob, os
from datetime import datetime
import pandas as pd

rows = []
for z in glob.glob(r"bhoonidhi_year\**\*.zip", recursive=True):
    name = os.path.basename(z)
    m = re.search(r"\d{2}[A-Za-z]{3}20\d{2}", name)
    if not m:
        continue
    sensor = ("AWIFS" if "AWIFS" in z.upper() else "LISS3" if "LISS3" in z.upper()
              else "EOS04" if "EOS-04" in z.upper() else "OTHER")
    rows.append(dict(sensor=sensor, date=datetime.strptime(m.group(0).upper(), "%d%b%Y").date(),
                     scene=name[:-4], gb=os.path.getsize(z) / 1e9))

df = pd.DataFrame(rows)
df.to_csv("scene_index.csv", index=False)
print(df.groupby("sensor").agg(scenes=("scene", "count"), dates=("date", "nunique"), GB=("gb", "sum")).round(1))
df["month"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m")
print("\nunique dates per month:")
print(df.groupby(["month", "sensor"])["date"].nunique().unstack(fill_value=0))
print("\nadhuri .part files:", glob.glob(r"bhoonidhi_year\**\*.part", recursive=True))