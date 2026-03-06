import ollama

ollama.generate(model='qwen3.5:2b',keep_alive=-1) # model bir kez yüklenir, sonraki çağrılarda tekrar yüklenmez

response = ollama.chat(model='qwen3.5:2b', messages=[
    {
        'role': 'user',
        'content': 'Why is the sky blue?',
    },
])
print(response['message']['content'] + "\n END OF RESPONSE\n")

response = ollama.chat(model='qwen3.5:2b', messages=[
    {
        'role': 'user',
        'content': 'Why is the sky blue?, explain it in Turkish',
    },
])
print(response['message']['content'] + "\n END OF RESPONSE\n")

response = ollama.chat(model='qwen3.5:2b', messages=[
    {
        'role': 'user',
        'content': 'Why is the sky blue?, explain it in Turkish, with only in 15 words',
    },
])
print(response['message']['content'] + "\n END OF RESPONSE\n")


ollama.generate(model='qwen3.5:2b',keep_alive=0)