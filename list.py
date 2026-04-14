import google.generativeai as genai

genai.configure(api_key="AIzaSyAoQuKW-lMcvG3Kc4Avs6q-qIBDAF-b_O8")

for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)