FROM node:24
WORKDIR /app
COPY . .
RUN npm install
CMD ["npx", "ts-node", "server/server.ts"]
