FROM eclipse-mosquitto:2

# Copy configuration
COPY mosquitto.conf /mosquitto/config/mosquitto.conf

# Generate password file (batch mode, non-interactive)
# Credentials: predict_sim / predict_sim_pass
RUN mosquitto_passwd -b -c /mosquitto/config/passwd predict_sim predict_sim_pass

# Ensure permissions
RUN chown -R mosquitto:mosquitto /mosquitto/config