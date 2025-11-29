import google.generativeai as genai

genai.configure(api_key="AIzaSyBbk3_WQRufc8dsR4JNvf4C2pAr3i-hLK4")

models = genai.list_models()
for m in models:
    print(m.name)
