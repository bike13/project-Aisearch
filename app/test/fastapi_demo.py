from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/index")
async def show_index():
    return {"message": "这是首页!"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello, {name}!"}


@app.post("/login")
async def login(username: str, password: str):
    return {"message": f"登录成功, 用户名: {username}, 密码: {password}"}


# 启动main函数
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
