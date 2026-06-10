import os
keys = ['GEMINI_API_KEY','OPENROUTER_API_KEY','GROQ_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','DEEPSEEK_API_KEY']
for k in keys:
    v = os.environ.get(k,'')
    if v:
        print(f'{k}: SET ({v[:20]}...)')
    else:
        print(f'{k}: NOT SET')
