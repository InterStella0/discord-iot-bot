CREATE DATABASE iot_discord;

CREATE TABLE device_info_view(
    device_id TEXT,
    author_id BIGINT,
    message_id BIGINT,
    channel_id BIGINT,
    PRIMARY KEY (device_id, author_id)
);