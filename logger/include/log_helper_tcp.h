#ifndef LOG_HELPER_TCP_H
#define LOG_HELPER_TCP_H

#include "log_helper_base.h"
#include <iostream>

class log_helper_tcp : public virtual log_helper_base {
    std::string server_ip;
    int32_t port = 0;

public:

    log_helper_tcp(const std::string &benchmark_name, const std::string &test_info)
            : log_helper_base(benchmark_name, test_info) {
        //TODO: read config file here and set the ip and the port

        //TODO: connect the server and request the log file name
        //must send the binary name and the hostname
    }

    uint8_t start_iteration() final {
        return 0;
    }

    uint8_t end_iteration() final {
        return 0;
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

    ~log_helper_base() {
        //TODO: write the destructor
    }
};

#endif //LOG_HELPER_TCP_H
