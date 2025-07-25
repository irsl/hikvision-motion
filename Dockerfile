FROM alpine:latest
RUN apk add openssl curl jq bash ffmpeg python3 py3-numpy py3-opencv py3-pip tzdata; \
    cp /usr/share/zoneinfo/Europe/Budapest /etc/localtime; \
	pip install --break-system-packages pyasyncore
ADD bin /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/smtp.py"]
