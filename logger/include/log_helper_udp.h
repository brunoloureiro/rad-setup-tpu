#ifndef LOG_HELPER_TCP_H
#define LOG_HELPER_TCP_H

#include <iostream>
#include <sys/types.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#include "log_helper_base.h"

namespace log_helper {
#define DEBUG 1
#define BUFFER_SIZE 1024
    /**
     * Based on the server messages
     */
    typedef enum {
        /**
         * Message types defined for the communication
         */
        CREATE_HEADER = 0,
        ITERATION_TIME = 1,
        ERROR_DETAIL = 2,
        INFO_DETAIL = 3,
        SDC_END = 4,
        TOO_MANY_ERRORS_PER_ITERATION = 5,
        TOO_MANY_INFOS_PER_ITERATION = 6,
        NORMAL_END = 7,
        SAME_ERROR_LAST_ITERATION = 8,

    } MessageType;

    class log_helper_tcp : public virtual log_helper_base {
        //TODO: this must be read from a file
        std::string server_ip;
        int32_t port;
        int32_t client_socket;
        struct sockaddr_in server_address;

        uint8_t send_message(std::vector<uint8_t> &message) {
            auto error = sendto(this->client_socket, message.data(), BUFFER_SIZE,
                                MSG_CONFIRM, (const struct sockaddr *) &this->server_address,
                                sizeof(this->server_address));
            if (error < 0) {
                std::throw_with_nested(EXCEPTION_LINE("Could not send the message"));
            }
            return 1;
        }

    public:

        log_helper_tcp(const std::string &benchmark_name, const std::string &test_info)
                : log_helper_base(benchmark_name, test_info), server_address({}) {
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
                std::throw_with_nested(EXCEPTION_LINE("Could not create a socket"));
            }

#ifdef DEBUG
            std::cout << "Connecting to server..." << std::endl;
#endif
        }

        uint8_t start_iteration() final {
            return log_helper_base::start_iteration();
        }

        uint8_t end_iteration() final {
            log_helper_base::end_iteration();
            if (!this->end_iteration_string.empty()) {
                static std::vector<uint8_t> buffer(BUFFER_SIZE);
                std::fill(buffer.begin(), buffer.end(), 0);
                buffer[0] = ITERATION_TIME;
                std::copy(this->end_iteration_string.begin(),
                          this->end_iteration_string.end(),
                          buffer.begin() + 1);
                return this->send_message(buffer);
            }


            return 1;
        }

        uint8_t log_error_count(size_t kernel_errors) final {
            return 0;
        }

        uint8_t log_info_count(size_t info_count) final {
            return 0;
        }

        uint8_t log_error_detail(const std::string &string) final {
            std::cout << string << std::endl;
            return 0;
        }

        uint8_t log_info_detail(const std::string &string) final {
            return 0;
        }
    };
}

#endif //LOG_HELPER_TCP_H
