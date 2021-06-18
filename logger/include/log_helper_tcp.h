#ifndef LOG_HELPER_TCP_H
#define LOG_HELPER_TCP_H

#include <iostream>
#include <zmq.hpp>
#include "log_helper_base.h"

namespace log_helper {
#define DEBUG 1

    class log_helper_tcp : public virtual log_helper_base {
        //TODO: this must be read from a file
        std::string server_ip = "tcp://localhost:5555";
        int32_t port = 0;
        zmq::socket_t socket;
        zmq::context_t context;
    public:

        log_helper_tcp(const std::string &benchmark_name, const std::string &test_info)
                : log_helper_base(benchmark_name, test_info) {

            //  Prepare our context and socket
            this->context = zmq::context_t(1);
            this->socket = zmq::socket_t(context, ZMQ_REQ);

#ifdef DEBUG
            std::cout << "Connecting to hello world server..." << std::endl;
#endif
            socket.connect(this->server_ip);
        }

        uint8_t start_iteration() final {
            log_helper_base::start_iteration();

            const std::string start_it = "START_IT";
            zmq::message_t request(start_it.begin(), start_it.end());
            size_t sent_size = *this->socket.send(request, zmq::send_flags::none);
            return sent_size != start_it.size();
        }

        uint8_t end_iteration() final {
            log_helper_base::end_iteration();
            const std::string end_it = "END_IT";
            size_t sent_size = 0;
            if (!this->end_iteration_generated_string.empty()) {
                zmq::message_t request(end_it.begin(), end_it.end());
                sent_size = *this->socket.send(request, zmq::send_flags::none);
            }
            return sent_size != end_it.size();
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

        ~log_helper_tcp() override {
            // Close the connection
            this->socket.close();
        }
    };
}

#endif //LOG_HELPER_TCP_H
