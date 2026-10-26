import zipfile
z = r"D:\Embedding-Foundational-Model\bhoonidhi_year\EOS-04_SAR-MRS_L2B\E04_SAR_MRS_05JAN2025_005000558909_15965_STUC00ZTD_21240_7_DH_D_R_N25120_E088158.zip"
zf = zipfile.ZipFile(z)
n = [n for n in zf.namelist() if n.endswith("product.xml")][0]
open(r"D:\Embedding-Foundational-Model\product.xml", "wb").write(zf.read(n))
print("saved")