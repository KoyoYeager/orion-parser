module;
#include "factor.hpp"
export module sample.scale;

export namespace sample::math {
    enum class Mode : unsigned { skip, add = 2, };
    using Count = unsigned long;
    constexpr Count scaled(Count value, Mode mode) noexcept {
        return mode == Mode::add ? value * SCALE_FACTOR + 1 : 0;
    }
}

module :private;
constexpr sample::math::Count internal_value = 0b10'01;
