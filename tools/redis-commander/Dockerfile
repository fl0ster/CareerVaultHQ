# redis-commander (browser UI for Redis) built from the multi-arch Node base so it
# runs on the Raspberry Pi 2 (arm/v7). The upstream rediscommander/redis-commander
# and datagrok/p3x-redis-ui images are amd64-only.
FROM node:18-alpine
RUN npm install -g redis-commander && npm cache clean --force
EXPOSE 8081
ENTRYPOINT ["redis-commander", "--port", "8081"]
