// frontend/src/api/client.ts —— axios 封装，注入 JWT
import axios from 'axios'

const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use(cfg => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 统一错误处理：401 清除 token 跳登录
client.interceptors.response.use(
  resp => resp,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default client
