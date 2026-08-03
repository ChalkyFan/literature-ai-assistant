"""Local configuration - override settings, API keys, registration keys"""
# DeepSeek API 配置
DEEPSEEK_API_KEY = "sk-your-key-here"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-pro"

# 注册密钥（首次使用时修改为自己的密钥）
REGISTER_KEY = "your-register-key"
ADMIN_REGISTER_KEY = "your-admin-key"

# Gemini API configuration - Google AI Studio
GEMINI_API_KEY = "your-gemini-api-key-here"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-001:generateContent"
GEMINI_MODEL = "gemini-2.5-flash-001"
