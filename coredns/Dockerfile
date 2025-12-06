FROM coredns/coredns:latest

COPY Corefile /etc/coredns/Corefile

EXPOSE 53/udp 53/tcp

CMD ["-conf", "/etc/coredns/Corefile"]
