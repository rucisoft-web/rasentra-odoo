FROM odoo:18.0

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/rasentra-requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/rasentra-requirements.txt

COPY --chown=odoo:odoo oca /mnt/rasentra/oca
COPY --chown=odoo:odoo addons /mnt/rasentra/addons
COPY --chown=odoo:odoo scripts /mnt/rasentra/scripts
COPY --chown=odoo:odoo config /etc/odoo/rasentra

USER odoo
