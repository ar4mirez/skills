FROM gcc:14
WORKDIR /app
COPY . .
RUN apt-get update && apt-get install -y cmake && cmake -B build && cmake --build build
EXPOSE 8080
CMD ["./build/inventory"]
