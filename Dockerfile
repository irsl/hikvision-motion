FROM alpine:3.19
# alpine 3.19 is the latest alpine version with python 3.11 which in turn has smtpd as a built-in core package
RUN apk add openssl curl jq bash ffmpeg python3 py3-numpy py3-opencv tzdata; \
    cp /usr/share/zoneinfo/Europe/Budapest /etc/localtime
ADD bin /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/smtp.py"]
