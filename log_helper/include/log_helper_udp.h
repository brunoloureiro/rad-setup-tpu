#ifndef LOG_HELPER_TCP_H
#define LOG_HELPER_TCP_H

#include <iostream>
#include <sys/types.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#include "log_helper_base.h"

namespace log_helper {

#define BUFFER_SIZE 1024

    class log_helper_udp : public virtual log_helper_base {
        std::string server_ip;
        int32_t port;
        int32_t client_socket;
        struct sockaddr_in server_address;

        void send_message(std::string &message) {
            auto error = sendto(this->client_socket, message.data(), BUFFER_SIZE,
                                MSG_CONFIRM, (const struct sockaddr *) &this->server_address,
                                sizeof(this->server_address));

            if (error < 0) {
                std::cerr << EXCEPTION_LINE("Could not send the message " + message) << std::endl;
            }
        }


    public:

        log_helper_udp(const std::string &benchmark_name, const std::string &test_info)
                : log_helper_base(), server_address({}) {
            this->server_ip = this->configuration_parameters["server_ip"];
            this->port = std::stoi(this->configuration_parameters["port"]);
            //  Prepare our context and socket
            // Filling server information
            this->client_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);

            this->server_address.sin_family = AF_INET;
            this->server_address.sin_port = htons(this->port);
            // this->server_address.sin_addr.s_addr = INADDR_ANY;
            // store this IP address in sa:
            inet_pton(AF_INET, this->server_ip.c_str(), &(this->server_address.sin_addr.s_addr));
            if (client_socket < -1) {
                std::cerr << EXCEPTION_LINE("Could not create a socket") << std::endl;
            }
        }

        void start_iteration() final {
            log_helper_base::start_iteration();
        }

        void end_iteration() final {
            log_helper_base::end_iteration();
            if (!this->end_iteration_string.empty()) {
                this->send_message(this->end_iteration_string);
            }
        }

        void log_error_count(size_t error_count) final {
            log_helper_base::log_error_count(error_count);
            if (error_count > 0) {
                this->send_message(this->log_error_count_str);
            }
        }

        void log_info_count(size_t info_count) final {
            log_helper_base::log_info_count(info_count);
            if (info_count > 0) {
                this->send_message(this->log_error_count_str);
            }
        }

        void log_error_detail(std::string &error_detail) final {
            log_helper_base::log_error_detail(error_detail);
            if (!this->log_error_detail_str.empty()) {
                this->send_message(this->log_error_detail_str);
            }
        }

        void log_info_detail(std::string &info_detail) final {
            log_helper_base::log_info_detail(info_detail);
            if (!this->log_info_detail_str.empty()) {
                this->send_message(this->log_info_detail_str);
            }
        }

        ~log_helper_udp() override {
            auto s = std::string("#END");
            this->send_message(s);
        }
    };
}

#endif //LOG_HELPER_TCP_H
