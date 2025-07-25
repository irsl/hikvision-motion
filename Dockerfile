FROM alpine:latest
RUN apk add openssl curl jq bash ffmpeg python3 py3-numpy py3-aiosmtpd py3-opencv tzdata; \
    cp /usr/share/zoneinfo/Europe/Budapest /etc/localtime
ADD bin /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/smtp.py"]
