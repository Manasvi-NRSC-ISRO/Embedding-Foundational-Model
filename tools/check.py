import zipfile
z = r"bhoonidhi_year\EOS-04_SAR-MRS_L2B\E04_SAR_MRS_05JAN2025_005000558909_15965_STUC00ZTD_21240_7_DH_D_R_N25120_E088158.zip"
zf = zipfile.ZipFile(z)
for n in zf.namelist():
    if n.endswith(("BAND_META.txt", "_HH_level_2B_grid.txt", "product.xml")):
        t = zf.read(n).decode(errors="replace")
        print("-----", n)
        print(t[2800:] if n.endswith("BAND_META.txt") else t[:2000])