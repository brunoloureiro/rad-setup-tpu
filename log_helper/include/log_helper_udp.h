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

    class log_helper_udp : public virtual log_helper_base {
        //TODO: this must be read from a file
        std::string server_ip;
        int32_t port;
        int32_t client_socket;
        struct sockaddr_in server_address;

        void send_message(std::string &message, MessageType message_type) {
            std::string data_string = std::to_string(message_type) + message;

            auto error = sendto(this->client_socket, data_string.data(), BUFFER_SIZE,
                                MSG_CONFIRM, (const struct sockaddr *) &this->server_address,
                                sizeof(this->server_address));

            if (error < 0) {
                std::cerr << EXCEPTION_LINE("Could not send the message " + data_string) << std::endl;
            }
        }

        void start_log_file(const std::string &benchmark_name, const std::string &test_info) {
            // The header message will be organized in the follow manner
            // | 1 byte message type | 1 byte benchmark_name string size | benchmark_name string | header content
            auto name_size = benchmark_name.size();
            if (name_size > 255) {
                std::cerr << EXCEPTION_LINE("BENCHMARK_NAME cannot be larger than 1 byte") << std::endl;
            }
            auto final_message = std::to_string(name_size) + benchmark_name + test_info;

            this->send_message(final_message, CREATE_HEADER);
        }

    public:

        log_helper_udp(const std::string &benchmark_name, const std::string &test_info)
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
                std::cerr << EXCEPTION_LINE("Could not create a socket") << std::endl;
            }

            this->start_log_file(benchmark_name, test_info);
        }

        void start_iteration() final {
            log_helper_base::start_iteration();
        }

        void end_iteration() final {
            log_helper_base::end_iteration();
            if (!this->end_iteration_string.empty()) {
                this->send_message(this->end_iteration_string, ITERATION_TIME);
            }
        }

        void log_error_count(size_t kernel_errors) final {
        }

        void log_info_count(size_t info_count) final {
        }

        void log_error_detail(const std::string &string) final {
            std::cout << string << std::endl;
        }

        void log_info_detail(const std::string &string) final {
        }
    };
}

#endif //LOG_HELPER_TCP_H
